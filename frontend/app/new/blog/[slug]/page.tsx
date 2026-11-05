import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { BlogArticle } from "@/components/site/BlogViews";
import { POSTS, findPost, postPath } from "@/components/site/blog-posts";

// Only published slugs exist; anything else is a 404.
export const dynamicParams = false;

export function generateStaticParams() {
  return POSTS.map((p) => ({ slug: p.slug }));
}

export function generateMetadata({ params }: { params: { slug: string } }): Metadata {
  const post = findPost(params.slug);
  if (!post) return {};
  return {
    title: { absolute: `${post.seoTitle ?? post.title} | Anril AI` },
    description: post.description,
    alternates: { canonical: postPath(post.slug) },
    openGraph: { type: "article", publishedTime: post.published, modifiedTime: post.updated, authors: [post.author] },
  };
}

export default function BlogPostPage({ params }: { params: { slug: string } }) {
  const post = findPost(params.slug);
  if (!post) notFound();
  return <BlogArticle post={post} />;
}
